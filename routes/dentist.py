import re
import unicodedata
from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, aliased

from core.config import CLINIC_CLOSE_TIME, CLINIC_OPEN_TIME
from database import get_db
from dependencies.autenticacao import require_roles
from models import (
    Appointment,
    ClinicalDocument,
    ClinicalDocumentAudit,
    DentalChartEntry,
    Patient,
    TreatmentPlan,
    TreatmentPlanAudit,
    TreatmentPlanProcedure,
    User,
)
from schemas.dentist import (
    DentistAppointment,
    DentistAttendanceHistoryChartEntry,
    DentistAttendanceHistoryDocument,
    DentistAttendanceHistoryItem,
    DentistAttendanceHistoryMetrics,
    DentistAttendanceHistoryResponse,
    DentistClinicalDocumentAuditResponse,
    DentistClinicalDocumentCreate,
    DentistClinicalDocumentRegistryResponse,
    DentistClinicalDocumentResponse,
    DentistClinicalDocumentSummary,
    DentistClinicalDocumentUpdate,
    DentistDentalChartEntry,
    DentistDentalChartEntryCreate,
    DentistDentalChartPatient,
    DentistDentalChartResponse,
    DentistDashboardResponse,
    DentistPatientAppointment,
    DentistPatientItem,
    DentistPatientMetrics,
    DentistPatientRegistryResponse,
    DentistTreatmentPlanAuditResponse,
    DentistTreatmentPlanCreate,
    DentistTreatmentPlanRegistryResponse,
    DentistTreatmentPlanResponse,
    DentistTreatmentPlanUpdate,
    DentistTreatmentPlanSummary,
    DentistTreatmentProcedureAdd,
    DentistTreatmentProcedureInput,
    DentistTreatmentProcedureResponse,
    DentistTreatmentProcedureUpdate,
)

router = APIRouter(
    prefix="/api/dentist",
    tags=["Portal da Dentista"],
    dependencies=[Depends(require_roles("dentist"))],
)


def _authorize_dentist_patient(
    patient_id: int,
    db: Session,
    user: User,
) -> Patient:
    patient = (
        db.query(Patient)
        .join(Appointment, Appointment.patient_id == Patient.id)
        .filter(
            Patient.id == patient_id,
            Patient.clinic_id == user.clinic_id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
        )
        .first()
    )
    if patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")
    return patient


def _dental_chart_entry_response(
    entry: DentalChartEntry,
    dentist_name: str,
    appointment_date: date | None,
) -> DentistDentalChartEntry:
    return DentistDentalChartEntry(
        id=entry.id,
        request_id=entry.request_id,
        supersedes_entry_id=entry.supersedes_entry_id,
        tooth_number=entry.tooth_number,
        record_type=entry.record_type,
        label=entry.label,
        status=entry.status,
        surfaces=entry.surfaces,
        note=entry.note,
        record_date=entry.record_date,
        created_at=entry.created_at,
        dentist_id=entry.dentist_id,
        dentist_name=dentist_name,
        appointment_id=entry.appointment_id,
        appointment_date=appointment_date,
    )


def _dental_chart_query(patient_id: int, user: User, db: Session):
    return (
        db.query(DentalChartEntry, User.name, Appointment.appointment_date)
        .join(User, User.id == DentalChartEntry.dentist_id)
        .outerjoin(Appointment, Appointment.id == DentalChartEntry.appointment_id)
        .filter(
            DentalChartEntry.patient_id == patient_id,
            DentalChartEntry.clinic_id == user.clinic_id,
        )
    )


def _matches_dental_chart_payload(
    entry: DentalChartEntry,
    payload: DentistDentalChartEntryCreate,
) -> bool:
    return (
        entry.tooth_number == payload.tooth_number
        and entry.record_type == payload.record_type
        and entry.label == payload.label
        and entry.status == payload.status
        and entry.surfaces == payload.surfaces
        and entry.note == payload.note
        and entry.record_date == payload.record_date
        and entry.appointment_id == payload.appointment_id
        and entry.supersedes_entry_id == payload.supersedes_entry_id
    )


@router.get(
    "/patients/{patient_id}/odontogram",
    response_model=DentistDentalChartResponse,
)
def dentist_patient_odontogram(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistDentalChartResponse:
    patient = _authorize_dentist_patient(patient_id, db, user)
    rows = (
        _dental_chart_query(patient_id, user, db)
        .order_by(DentalChartEntry.created_at.desc(), DentalChartEntry.id.desc())
        .all()
    )
    entries = [
        _dental_chart_entry_response(entry, dentist_name, appointment_date)
        for entry, dentist_name, appointment_date in rows
    ]
    latest_entry_id = max((entry.id for entry in entries), default=None)
    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
        )
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
        .limit(100)
        .all()
    )
    return DentistDentalChartResponse(
        patient=DentistDentalChartPatient(
            id=patient.id,
            name=patient.name,
            birth_date=patient.birth_date,
            last_updated=entries[0].created_at if entries else None,
        ),
        entries=entries,
        latest_entry_id=latest_entry_id,
        appointments=[
            DentistPatientAppointment(
                id=appointment.id,
                appointment_date=appointment.appointment_date,
                appointment_time=appointment.appointment_time,
                duration_minutes=appointment.duration_minutes,
                procedure=appointment.procedure,
                confirmation_status=appointment.confirmation_status,
                status=appointment.status,
            )


            for appointment in appointments
        ],
    )


@router.get(
    "/patients/{patient_id}/odontogram/history",
    response_model=list[DentistDentalChartEntry],
)
def dentist_patient_odontogram_history(
    patient_id: int,
    tooth_number: str | None = Query(default=None, pattern=r"^[1-8][1-8]$"),
    record_type: str | None = Query(default=None, pattern="^(condition|procedure)$"),
    dentist_id: int | None = Query(default=None, ge=1),
    since: date | None = None,
    until: date | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> list[DentistDentalChartEntry]:
    _authorize_dentist_patient(patient_id, db, user)
    if since and until and since > until:
        raise HTTPException(status_code=422, detail="O início deve preceder o fim.")
    query = _dental_chart_query(patient_id, user, db)
    if tooth_number:
        query = query.filter(DentalChartEntry.tooth_number == tooth_number)
    if record_type:
        query = query.filter(DentalChartEntry.record_type == record_type)
    if dentist_id:
        query = query.filter(DentalChartEntry.dentist_id == dentist_id)
    if since:
        query = query.filter(DentalChartEntry.record_date >= since)
    if until:
        query = query.filter(DentalChartEntry.record_date <= until)
    rows = query.order_by(
        DentalChartEntry.created_at.desc(), DentalChartEntry.id.desc()
    ).limit(200).all()
    return [
        _dental_chart_entry_response(entry, dentist_name, appointment_date)
        for entry, dentist_name, appointment_date in rows
    ]


@router.post(
    "/patients/{patient_id}/odontogram",
    response_model=DentistDentalChartEntry,
    status_code=status.HTTP_201_CREATED,
)
def create_dentist_patient_odontogram_entry(
    patient_id: int,
    payload: DentistDentalChartEntryCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistDentalChartEntry:
    _authorize_dentist_patient(patient_id, db, user)
    existing_entry = (
        db.query(DentalChartEntry)
        .filter(DentalChartEntry.request_id == payload.request_id)
        .first()
    )
    if existing_entry is not None:
        if (
            existing_entry.patient_id != patient_id
            or existing_entry.clinic_id != user.clinic_id
            or existing_entry.dentist_id != user.id
            or not _matches_dental_chart_payload(existing_entry, payload)
        ):
            raise HTTPException(
                status_code=409,
                detail="Identificador de registro já utilizado ou conteúdo divergente.",
            )
        return _dental_chart_entry_response(
            existing_entry,
            user.name,
            db.query(Appointment.appointment_date)
            .filter(Appointment.id == existing_entry.appointment_id)
            .scalar()
            if existing_entry.appointment_id else None,
        )
    latest_entry_id = (
        db.query(func.max(DentalChartEntry.id))
        .filter(
            DentalChartEntry.patient_id == patient_id,
            DentalChartEntry.clinic_id == user.clinic_id,
        )
        .scalar()
    )
    if payload.expected_latest_id != latest_entry_id:
        raise HTTPException(
            status_code=409,
            detail="O odontograma foi atualizado. Atualize os dados antes de salvar.",
        )
    if payload.record_date > date.today():
        raise HTTPException(
            status_code=422,
            detail="A data do registro não pode estar no futuro.",
        )
    appointment = None
    superseded_entry = None
    if payload.supersedes_entry_id is not None:
        superseded_entry = (
            db.query(DentalChartEntry)
            .filter(
                DentalChartEntry.id == payload.supersedes_entry_id,
                DentalChartEntry.patient_id == patient_id,
                DentalChartEntry.clinic_id == user.clinic_id,
                DentalChartEntry.record_type == "procedure",
            )
            .first()
        )
        if superseded_entry is None:
            raise HTTPException(
                status_code=404,
                detail="Procedimento não encontrado para este paciente.",
            )
        allowed_transitions = {
            "planned": {"in_progress", "completed", "cancelled"},
            "in_progress": {"completed", "cancelled"},
        }
        already_updated = (
            db.query(DentalChartEntry.id)
            .filter(DentalChartEntry.supersedes_entry_id == superseded_entry.id)
            .first()
        )
        if (
            already_updated is not None
            or payload.status not in allowed_transitions.get(superseded_entry.status, set())
            or payload.tooth_number != superseded_entry.tooth_number
            or payload.label != superseded_entry.label
            or payload.surfaces != superseded_entry.surfaces
        ):
            raise HTTPException(
                status_code=422,
                detail="A atualização não corresponde a uma transição permitida para este procedimento.",
            )
    if payload.appointment_id is not None:
        appointment = (
            db.query(Appointment)
            .filter(
                Appointment.id == payload.appointment_id,
                Appointment.patient_id == patient_id,
                Appointment.clinic_id == user.clinic_id,
                Appointment.dentist_id == user.id,
            )
            .first()
        )
        if appointment is None:
            raise HTTPException(
                status_code=404,
                detail="Atendimento não encontrado para este paciente.",
            )
    if payload.status == "completed":
        if appointment is None or appointment.status != "Concluída":
            raise HTTPException(
                status_code=422,
                detail="Vincule um atendimento concluído para registrar o procedimento como realizado.",
            )

    entry = DentalChartEntry(
        request_id=payload.request_id,
        supersedes_entry_id=payload.supersedes_entry_id,
        clinic_id=user.clinic_id,
        patient_id=patient_id,
        dentist_id=user.id,
        appointment_id=appointment.id if appointment else None,
        tooth_number=payload.tooth_number,
        record_type=payload.record_type,
        label=payload.label,
        status=payload.status,
        surfaces=payload.surfaces,
        note=payload.note,
        record_date=payload.record_date,
    )
    db.add(entry)
    try:
        db.commit()
    except IntegrityError as error:
        db.rollback()
        existing_entry = (
            db.query(DentalChartEntry)
            .filter(DentalChartEntry.request_id == payload.request_id)
            .first()
        )
        if (
            existing_entry is None
            or existing_entry.patient_id != patient_id
            or existing_entry.clinic_id != user.clinic_id
            or existing_entry.dentist_id != user.id
            or not _matches_dental_chart_payload(existing_entry, payload)
        ):
            raise HTTPException(
                status_code=409,
                detail="Não foi possível confirmar o registro. Atualize o odontograma.",
            ) from error
        return _dental_chart_entry_response(
            existing_entry,
            user.name,
            appointment.appointment_date if appointment else None,
        )
    db.refresh(entry)
    return _dental_chart_entry_response(
        entry,
        user.name,
        appointment.appointment_date if appointment else None,
    )


@router.get("/dashboard", response_model=DentistDashboardResponse)
def dentist_dashboard(
    appointment_date: date = Query(alias="date"),
    days: int = Query(default=7, ge=1, le=31),
    q: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistDashboardResponse:
    end_date = appointment_date + timedelta(days=days)
    query = (
        db.query(Appointment, Patient)
        .join(Patient, Patient.id == Appointment.patient_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
            Appointment.appointment_date >= appointment_date,
            Appointment.appointment_date < end_date,
        )
    )
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(Patient.name.ilike(term))

    rows = query.order_by(Appointment.appointment_date, Appointment.appointment_time).all()
    appointments = []
    for appointment, patient in rows:
        arrival_at = appointment.arrival_at
        if arrival_at and arrival_at.tzinfo is None:
            arrival_at = arrival_at.replace(tzinfo=timezone.utc)
        appointments.append(
            DentistAppointment(
                id=appointment.id,
                patient_id=patient.id,
                patient_name=patient.name,
                appointment_date=appointment.appointment_date,
                appointment_time=appointment.appointment_time,
                duration_minutes=appointment.duration_minutes,
                procedure=appointment.procedure,
                confirmation_status=appointment.confirmation_status,
                status=appointment.status,
                arrival_at=arrival_at.isoformat() if arrival_at else None,
                created_at=appointment.created_at,
            )
        )
    return DentistDashboardResponse(
        appointments=appointments,
        clinic_open_time=CLINIC_OPEN_TIME,
        clinic_close_time=CLINIC_CLOSE_TIME,
    )


def _normalized_search(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        "".join(char for char in decomposed if not unicodedata.combining(char)).split()
    )


@router.get("/patients", response_model=DentistPatientRegistryResponse)
def dentist_patients(
    q: str | None = None,
    has_upcoming_appointment: bool | None = None,
    last_visit: str | None = Query(
        default=None, pattern="^(30|90|older|never)$"
    ),
    sort_by: str = Query(
        default="name", pattern="^(name|last_appointment|next_appointment)$"
    ),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistPatientRegistryResponse:
    now = datetime.now()
    today = now.date()
    current_time = now.time()
    linked_patient_ids = (
        select(Appointment.patient_id)
        .where(
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
        )
        .distinct()
    )
    authorized_patients = (
        db.query(Patient)
        .filter(
            Patient.clinic_id == user.clinic_id,
            Patient.id.in_(linked_patient_ids),
        )
        .all()
    )
    appointment_rows = (
        db.query(Appointment)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
        )
        .order_by(Appointment.appointment_date, Appointment.appointment_time)
        .all()
    )
    appointments_by_patient: dict[int, list[Appointment]] = {}
    for appointment in appointment_rows:
        appointments_by_patient.setdefault(appointment.patient_id, []).append(appointment)

    rows = []
    for patient in authorized_patients:
        patient_appointments = appointments_by_patient[patient.id]
        past_completed = [
            appointment for appointment in patient_appointments
            if appointment.status == "Concluída"
            and appointment.appointment_date <= today
        ]
        upcoming = [
            appointment for appointment in patient_appointments
            if appointment.status not in {
                "Cancelada", "Reagendada", "Concluída", "Não compareceu"
            }
            and (
                appointment.appointment_date > today
                or (
                    appointment.appointment_date == today
                    and appointment.appointment_time >= current_time
                )
            )
        ]
        latest_completed = max(
            past_completed,
            key=lambda appointment: (appointment.appointment_date, appointment.appointment_time),
            default=None,
        )
        next_appointment = min(
            upcoming,
            key=lambda appointment: (appointment.appointment_date, appointment.appointment_time),
            default=None,
        )
        item = DentistPatientItem(
            id=patient.id,
            name=patient.name,
            cpf=patient.cpf,
            birth_date=patient.birth_date,
            phone=patient.phone,
            email=patient.email,
            last_appointment_date=(
                latest_completed.appointment_date if latest_completed else None
            ),
            next_appointment=(
                DentistPatientAppointment(
                    id=next_appointment.id,
                    appointment_date=next_appointment.appointment_date,
                    appointment_time=next_appointment.appointment_time,
                    duration_minutes=next_appointment.duration_minutes,
                    procedure=next_appointment.procedure,
                    confirmation_status=next_appointment.confirmation_status,
                    status=next_appointment.status,
                )
                if next_appointment else None
            ),
        )
        rows.append(item)

    if q and q.strip():
        search_text = _normalized_search(q)
        search_digits = re.sub(r"\D", "", q)
        rows = [
            item for item in rows
            if search_text in _normalized_search(item.name)
            or (search_digits and (
                search_digits in re.sub(r"\D", "", item.cpf or "")
                or search_digits in re.sub(r"\D", "", item.phone)
                or search_digits in str(item.id)
            ))
        ]
    if has_upcoming_appointment is not None:
        rows = [
            item for item in rows
            if (item.next_appointment is not None) == has_upcoming_appointment
        ]
    if last_visit:
        cutoff = today - timedelta(days=30 if last_visit == "30" else 90)
        if last_visit == "never":
            rows = [item for item in rows if item.last_appointment_date is None]
        elif last_visit == "older":
            rows = [
                item for item in rows
                if item.last_appointment_date is not None
                and item.last_appointment_date < cutoff
            ]
        else:
            rows = [
                item for item in rows
                if item.last_appointment_date is not None
                and item.last_appointment_date >= cutoff
            ]

    if sort_by == "last_appointment":
        rows.sort(
            key=lambda item: (item.last_appointment_date is not None, item.last_appointment_date or date.min),
            reverse=True,
        )
    elif sort_by == "next_appointment":
        rows.sort(
            key=lambda item: (
                item.next_appointment is None,
                item.next_appointment.appointment_date if item.next_appointment else date.max,
                item.next_appointment.appointment_time if item.next_appointment else time.max,
            )
        )
    else:
        rows.sort(key=lambda item: (_normalized_search(item.name), item.id))

    filtered_total = len(rows)
    filtered_upcoming = sum(item.next_appointment is not None for item in rows)
    return DentistPatientRegistryResponse(
        items=rows[offset:offset + limit],
        total=filtered_total,
        metrics=DentistPatientMetrics(
            total=filtered_total,
            with_upcoming_appointments=filtered_upcoming,
            in_treatment=None,
            with_pending_follow_up=None,
        ),
    )


@router.get(
    "/patients/{patient_id}/appointments",
    response_model=list[DentistPatientAppointment],
)
def dentist_patient_appointments(
    patient_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> list[DentistPatientAppointment]:
    authorized_patient = (
        db.query(Patient.id)
        .join(Appointment, Appointment.patient_id == Patient.id)
        .filter(
            Patient.id == patient_id,
            Patient.clinic_id == user.clinic_id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
        )
        .first()
    )
    if authorized_patient is None:
        raise HTTPException(status_code=404, detail="Paciente não encontrado.")

    appointments = (
        db.query(Appointment)
        .filter(
            Appointment.patient_id == patient_id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
            Appointment.appointment_date <= date.today(),
            Appointment.status == "Concluída",
        )
        .order_by(Appointment.appointment_date.desc(), Appointment.appointment_time.desc())
        .limit(50)
        .all()
    )
    return [
        DentistPatientAppointment(
            id=appointment.id,
            appointment_date=appointment.appointment_date,
            appointment_time=appointment.appointment_time,
            duration_minutes=appointment.duration_minutes,
            procedure=appointment.procedure,
            confirmation_status=appointment.confirmation_status,
            status=appointment.status,
        )
        for appointment in appointments
    ]


@router.get(
    "/appointment-history",
    response_model=DentistAttendanceHistoryResponse,
)
def dentist_appointment_history(
    q: str | None = Query(default=None, max_length=160),
    date_from: date | None = None,
    date_to: date | None = None,
    patient_id: int | None = Query(default=None, ge=1),
    appointment_status: str | None = Query(default=None, max_length=32),
    procedure: str | None = Query(default=None, max_length=120),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistAttendanceHistoryResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data inicial deve ser anterior ou igual à data final.",
        )

    appointments = (
        db.query(Appointment, Patient.name, User.name)
        .join(Patient, Patient.id == Appointment.patient_id)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
            Patient.clinic_id == user.clinic_id,
            Appointment.appointment_date <= date.today(),
        )
        .all()
    )
    if date_from:
        appointments = [
            row for row in appointments if row[0].appointment_date >= date_from
        ]
    if date_to:
        appointments = [
            row for row in appointments if row[0].appointment_date <= date_to
        ]
    if patient_id is not None:
        appointments = [
            row for row in appointments if row[0].patient_id == patient_id
        ]
    if appointment_status:
        appointments = [
            row for row in appointments if row[0].status == appointment_status
        ]
    if procedure and procedure.strip():
        procedure_search = _normalized_search(procedure)
        appointments = [
            row for row in appointments
            if procedure_search in _normalized_search(row[0].procedure)
        ]
    if q and q.strip():
        search_text = _normalized_search(q)
        search_digits = re.sub(r"\D", "", q)
        appointments = [
            row for row in appointments
            if search_text in _normalized_search(row[1])
            or search_text in _normalized_search(row[0].procedure)
            or search_text in _normalized_search(row[2])
            or (search_digits and (
                search_digits in str(row[0].id)
                or search_digits in str(row[0].patient_id)
            ))
        ]

    appointments.sort(
        key=lambda row: (
            row[0].appointment_date,
            row[0].appointment_time,
            row[0].id,
        ),
        reverse=order == "desc",
    )
    total = len(appointments)
    completed = [row for row in appointments if row[0].status == "Concluída"]
    completed_appointment_ids = [row[0].id for row in completed]
    superseding_entry = aliased(DentalChartEntry)
    completed_procedure_count = (
        db.query(func.count(DentalChartEntry.id))
        .filter(
            DentalChartEntry.clinic_id == user.clinic_id,
            DentalChartEntry.dentist_id == user.id,
            DentalChartEntry.appointment_id.in_(completed_appointment_ids),
            DentalChartEntry.record_type == "procedure",
            DentalChartEntry.status == "completed",
            ~db.query(superseding_entry.id)
            .filter(superseding_entry.supersedes_entry_id == DentalChartEntry.id)
            .exists(),
        )
        .scalar()
        if completed_appointment_ids else 0
    )

    page_rows = appointments[offset:offset + limit]
    page_appointment_ids = [row[0].id for row in page_rows]
    chart_entries = (
        db.query(DentalChartEntry, User.name)
        .join(User, User.id == DentalChartEntry.dentist_id)
        .filter(
            DentalChartEntry.clinic_id == user.clinic_id,
            DentalChartEntry.dentist_id == user.id,
            DentalChartEntry.appointment_id.in_(page_appointment_ids),
        )
        .order_by(DentalChartEntry.record_date.desc(), DentalChartEntry.id.desc())
        .all()
        if page_appointment_ids else []
    )
    entries_by_appointment: dict[int, list[tuple[DentalChartEntry, str]]] = {}
    for entry, dentist_name in chart_entries:
        entries_by_appointment.setdefault(entry.appointment_id, []).append(
            (entry, dentist_name)
        )
    page_entry_ids = [entry.id for entry, _ in chart_entries]
    superseded_entry_ids = {
        row[0]
        for row in (
            db.query(DentalChartEntry.supersedes_entry_id)
            .filter(
                DentalChartEntry.clinic_id == user.clinic_id,
                DentalChartEntry.dentist_id == user.id,
                DentalChartEntry.supersedes_entry_id.in_(page_entry_ids),
            )
            .all()
            if page_entry_ids else []
        )
    }

    document_drafts = (
        db.query(ClinicalDocument)
        .filter(
            ClinicalDocument.clinic_id == user.clinic_id,
            ClinicalDocument.dentist_id == user.id,
            ClinicalDocument.appointment_id.in_(page_appointment_ids),
            ClinicalDocument.status == "draft",
        )
        .order_by(ClinicalDocument.updated_at.desc())
        .all()
        if page_appointment_ids else []
    )
    drafts_by_appointment: dict[int, list[ClinicalDocument]] = {}
    for document in document_drafts:
        drafts_by_appointment.setdefault(document.appointment_id, []).append(document)

    items = []
    for appointment, patient_name, dentist_name in page_rows:
        linked_entries = entries_by_appointment.get(appointment.id, [])
        linked_documents = drafts_by_appointment.get(appointment.id, [])
        items.append(
            DentistAttendanceHistoryItem(
                id=appointment.id,
                appointment_date=appointment.appointment_date,
                appointment_time=appointment.appointment_time,
                duration_minutes=appointment.duration_minutes,
                procedure=appointment.procedure,
                confirmation_status=appointment.confirmation_status,
                status=appointment.status,
                arrival_at=appointment.arrival_at,
                patient_id=appointment.patient_id,
                patient_name=patient_name,
                dentist_id=appointment.dentist_id,
                dentist_name=dentist_name,
                chart_entries=[
                    DentistAttendanceHistoryChartEntry(
                        id=entry.id,
                        tooth_number=entry.tooth_number,
                        record_type=entry.record_type,
                        label=entry.label,
                        status=entry.status,
                        surfaces=entry.surfaces,
                        note=entry.note,
                        record_date=entry.record_date,
                        created_at=entry.created_at,
                        dentist_name=entry_dentist_name,
                        supersedes_entry_id=entry.supersedes_entry_id,
                        is_superseded=entry.id in superseded_entry_ids,
                    )
                    for entry, entry_dentist_name in linked_entries
                ],
                procedure_count=(
                    sum(
                        entry.record_type == "procedure"
                        and entry.status == "completed"
                        and entry.id not in superseded_entry_ids
                        for entry, _ in linked_entries
                    )
                    if appointment.status == "Concluída" else 0
                ),
                clinical_records_with_notes_count=sum(
                    bool(entry.note) for entry, _ in linked_entries
                ),
                clinical_documentation_status="unknown",
                document_drafts=[
                    DentistAttendanceHistoryDocument(
                        id=document.id,
                        title=document.title,
                        document_type=document.document_type,
                        status="draft",
                        updated_at=document.updated_at,
                    )
                    for document in linked_documents
                ],
            )
        )

    return DentistAttendanceHistoryResponse(
        items=items,
        total=total,
        metrics=DentistAttendanceHistoryMetrics(
            completed_attendances=len(completed),
            patients_attended=len({row[0].patient_id for row in completed}),
            completed_procedures_registered=completed_procedure_count,
            documentation_pending=None,
        ),
    )


def _treatment_plan_access_query(db: Session, user: User):
    authorized_patient_ids = select(Appointment.patient_id).where(
        Appointment.clinic_id == user.clinic_id,
        Appointment.dentist_id == user.id,
    ).distinct()
    return (
        db.query(TreatmentPlan, Patient.name, User.name)
        .join(Patient, Patient.id == TreatmentPlan.patient_id)
        .join(User, User.id == TreatmentPlan.dentist_id)
        .filter(
            TreatmentPlan.clinic_id == user.clinic_id,
            TreatmentPlan.dentist_id == user.id,
            Patient.clinic_id == user.clinic_id,
            Patient.id.in_(authorized_patient_ids),
        )
    )


def _get_dentist_treatment_plan(plan_id: int, db: Session, user: User):
    row = _treatment_plan_access_query(db, user).filter(TreatmentPlan.id == plan_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Plano de tratamento não encontrado.")
    return row


def _treatment_procedure_snapshot(procedure: TreatmentPlanProcedure) -> dict:
    return {
        "name": procedure.name,
        "category": procedure.category,
        "description": procedure.description,
        "tooth_number": procedure.tooth_number,
        "surfaces": procedure.surfaces,
        "priority": procedure.priority,
        "stage": procedure.stage,
        "notes": procedure.notes,
        "status": procedure.status,
        "sort_order": procedure.sort_order,
        "completed_odontogram_entry_id": procedure.completed_odontogram_entry_id,
    }


def _record_treatment_plan_audit(
    db: Session,
    plan_id: int,
    user: User,
    action: str,
    summary: str,
    procedure_id: int | None = None,
    before_data: dict | None = None,
    after_data: dict | None = None,
) -> None:
    db.add(
        TreatmentPlanAudit(
            plan_id=plan_id,
            dentist_id=user.id,
            procedure_id=procedure_id,
            action=action,
            summary=summary,
            before_data=before_data,
            after_data=after_data,
        )
    )


def _treatment_plan_response(
    plan: TreatmentPlan,
    patient_name: str,
    dentist_name: str,
    db: Session,
) -> DentistTreatmentPlanResponse:
    procedures = (
        db.query(TreatmentPlanProcedure)
        .filter(TreatmentPlanProcedure.plan_id == plan.id)
        .order_by(TreatmentPlanProcedure.sort_order, TreatmentPlanProcedure.id)
        .all()
    )
    eligible = [procedure for procedure in procedures if procedure.status != "cancelled"]
    completed_count = sum(procedure.status == "completed" for procedure in procedures)
    in_progress_count = sum(procedure.status == "in_progress" for procedure in procedures)
    pending_count = sum(procedure.status == "planned" for procedure in procedures)
    latest_history_id = db.query(func.max(TreatmentPlanAudit.id)).filter(
        TreatmentPlanAudit.plan_id == plan.id
    ).scalar()
    return DentistTreatmentPlanResponse(
        id=plan.id,
        version=plan.version,
        patient={"id": plan.patient_id, "name": patient_name},
        dentist_id=plan.dentist_id,
        dentist_name=dentist_name,
        name=plan.name,
        notes=plan.notes,
        status=plan.status,
        created_at=plan.created_at,
        updated_at=plan.updated_at,
        procedures=[
            DentistTreatmentProcedureResponse(
                id=procedure.id,
                version=procedure.version,
                name=procedure.name,
                category=procedure.category,
                description=procedure.description,
                tooth_number=procedure.tooth_number,
                surfaces=procedure.surfaces,
                priority=procedure.priority,
                stage=procedure.stage,
                notes=procedure.notes,
                status=procedure.status,
                sort_order=procedure.sort_order,
                completed_odontogram_entry_id=procedure.completed_odontogram_entry_id,
                created_at=procedure.created_at,
                updated_at=procedure.updated_at,
            )
            for procedure in procedures
        ],
        procedure_count=len(procedures),
        completed_count=completed_count,
        in_progress_count=in_progress_count,
        pending_count=pending_count,
        progress_percent=(
            round(completed_count / len(eligible) * 100) if eligible else None
        ),
        latest_history_id=latest_history_id,
    )


@router.get(
    "/treatment-plans",
    response_model=DentistTreatmentPlanRegistryResponse,
)
def dentist_treatment_plans(
    q: str | None = None,
    plan_status: str | None = Query(
        default=None, alias="status",
        pattern="^(draft|in_progress|completed|cancelled)$",
    ),
    patient_id: int | None = Query(default=None, ge=1),
    procedure_status: str | None = Query(
        default=None, pattern="^(planned|in_progress|completed|cancelled)$"
    ),
    category: str | None = Query(default=None, max_length=80),
    has_pending: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort_by: str = Query(default="created_at", pattern="^(created_at|name|patient)$"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentPlanRegistryResponse:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="O início deve preceder o fim.")

    accessible_rows = _treatment_plan_access_query(db, user).all()
    all_plans = [row[0] for row in accessible_rows]
    metrics = DentistTreatmentPlanSummary(
        total=len(all_plans),
        in_progress=(
            db.query(func.count(func.distinct(TreatmentPlanProcedure.plan_id)))
            .filter(
                TreatmentPlanProcedure.plan_id.in_([plan.id for plan in all_plans]),
                TreatmentPlanProcedure.status == "in_progress",
            )
            .scalar()
            if all_plans else 0
        ),
        awaiting_approval=None,
        completed=sum(plan.status == "completed" for plan in all_plans),
    )

    rows = accessible_rows
    if q and q.strip():
        search_text = _normalized_search(q)
        search_digits = re.sub(r"\D", "", q)
        rows = [
            row for row in rows
            if search_text in _normalized_search(row[0].name)
            or search_text in _normalized_search(row[1])
            or (search_digits and (
                search_digits in str(row[0].id)
                or search_digits in str(row[0].patient_id)
            ))
        ]
    if plan_status:
        rows = [row for row in rows if row[0].status == plan_status]
    if patient_id is not None:
        rows = [row for row in rows if row[0].patient_id == patient_id]
    if date_from:
        rows = [row for row in rows if row[0].created_at.date() >= date_from]
    if date_to:
        rows = [row for row in rows if row[0].created_at.date() <= date_to]
    if procedure_status:
        rows = [
            row for row in rows
            if db.query(TreatmentPlanProcedure.id)
            .filter(
                TreatmentPlanProcedure.plan_id == row[0].id,
                TreatmentPlanProcedure.status == procedure_status,
            )
            .first() is not None
        ]
    if category and category.strip():
        normalized_category = _normalized_search(category)
        category_rows = (
            db.query(TreatmentPlanProcedure.plan_id, TreatmentPlanProcedure.category)
            .filter(
                TreatmentPlanProcedure.plan_id.in_([row[0].id for row in rows]),
                TreatmentPlanProcedure.category.is_not(None),
            )
            .all()
            if rows else []
        )
        matching_plan_ids = {
            plan_id
            for plan_id, procedure_category in category_rows
            if _normalized_search(procedure_category or "") == normalized_category
        }
        rows = [row for row in rows if row[0].id in matching_plan_ids]
    if has_pending is not None:
        rows = [
            row for row in rows
            if (
                db.query(TreatmentPlanProcedure.id)
                .filter(
                    TreatmentPlanProcedure.plan_id == row[0].id,
                    TreatmentPlanProcedure.status.in_(("planned", "in_progress")),
                )
                .first() is not None
            ) == has_pending
        ]

    if sort_by == "name":
        rows.sort(key=lambda row: (_normalized_search(row[0].name), row[0].id))
    elif sort_by == "patient":
        rows.sort(key=lambda row: (_normalized_search(row[1]), row[0].id))
    else:
        rows.sort(key=lambda row: (row[0].created_at, row[0].id), reverse=True)

    total = len(rows)
    page_rows = rows[offset:offset + limit]
    return DentistTreatmentPlanRegistryResponse(
        items=[
            _treatment_plan_response(plan, patient_name, dentist_name, db)
            for plan, patient_name, dentist_name in page_rows
        ],
        total=total,
        metrics=metrics,
    )


@router.post(
    "/treatment-plans",
    response_model=DentistTreatmentPlanResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dentist_treatment_plan(
    payload: DentistTreatmentPlanCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentPlanResponse:
    patient = _authorize_dentist_patient(payload.patient_id, db, user)
    plan = TreatmentPlan(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        dentist_id=user.id,
        name=payload.name,
        notes=payload.notes,
        status="draft",
    )
    db.add(plan)
    db.flush()
    _record_treatment_plan_audit(
        db, plan.id, user, "plan_created", "Plano criado como rascunho.",
        after_data={"name": plan.name, "status": plan.status},
    )
    for position, item in enumerate(payload.procedures):
        procedure = TreatmentPlanProcedure(
            plan_id=plan.id,
            name=item.name,
            category=item.category,
            description=item.description,
            tooth_number=item.tooth_number,
            surfaces=item.surfaces,
            priority=item.priority,
            stage=item.stage,
            notes=item.notes,
            status="planned",
            sort_order=item.sort_order if item.sort_order else position,
        )
        db.add(procedure)
        db.flush()
        _record_treatment_plan_audit(
            db, plan.id, user, "procedure_added", f"Procedimento “{procedure.name}” incluído.",
            procedure_id=procedure.id, after_data=_treatment_procedure_snapshot(procedure),
        )
    db.commit()
    db.refresh(plan)
    return _treatment_plan_response(plan, patient.name, user.name, db)


@router.get(
    "/treatment-plans/{plan_id}",
    response_model=DentistTreatmentPlanResponse,
)
def dentist_treatment_plan_detail(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentPlanResponse:
    plan, patient_name, dentist_name = _get_dentist_treatment_plan(plan_id, db, user)
    return _treatment_plan_response(plan, patient_name, dentist_name, db)


@router.patch(
    "/treatment-plans/{plan_id}",
    response_model=DentistTreatmentPlanResponse,
)
def update_dentist_treatment_plan(
    plan_id: int,
    payload: DentistTreatmentPlanUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentPlanResponse:
    plan, patient_name, dentist_name = _get_dentist_treatment_plan(plan_id, db, user)
    if plan.version != payload.version:
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize os dados antes de salvar.")
    if plan.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Este plano está encerrado e não pode ser alterado.")

    before = {"name": plan.name, "notes": plan.notes, "status": plan.status}
    updates = {}
    fields_set = payload.model_fields_set
    if "name" in fields_set and payload.name is not None:
        updates["name"] = payload.name
    if "notes" in fields_set:
        updates["notes"] = payload.notes
    if payload.action == "start":
        if plan.status != "draft":
            raise HTTPException(status_code=409, detail="Somente rascunhos podem ser iniciados.")
        procedure_count = db.query(func.count(TreatmentPlanProcedure.id)).filter(
            TreatmentPlanProcedure.plan_id == plan.id
        ).scalar()
        if not procedure_count:
            raise HTTPException(status_code=422, detail="Inclua ao menos um procedimento antes de iniciar.")
        updates["status"] = "in_progress"
    elif payload.action == "cancel":
        updates["status"] = "cancelled"
    if updates:
        result = db.execute(
            update(TreatmentPlan)
            .where(TreatmentPlan.id == plan.id, TreatmentPlan.version == payload.version)
            .values(**updates, version=TreatmentPlan.version + 1, updated_at=func.now())
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="O plano mudou. Atualize os dados antes de salvar.")
        db.refresh(plan)
        after = {"name": plan.name, "notes": plan.notes, "status": plan.status}
        action = f"plan_{payload.action}" if payload.action else "plan_updated"
        summary = {
            "start": "Plano iniciado pela dentista.",
            "cancel": "Plano cancelado pela dentista.",
        }.get(payload.action, "Dados gerais do plano atualizados.")
        _record_treatment_plan_audit(
            db, plan.id, user, action, summary, before_data=before, after_data=after
        )
        db.commit()
        db.refresh(plan)
    return _treatment_plan_response(plan, patient_name, dentist_name, db)


@router.post(
    "/treatment-plans/{plan_id}/procedures",
    response_model=DentistTreatmentProcedureResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_dentist_treatment_plan_procedure(
    plan_id: int,
    payload: DentistTreatmentProcedureAdd,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentProcedureResponse:
    plan, _patient_name, _dentist_name = _get_dentist_treatment_plan(plan_id, db, user)
    if plan.status not in {"draft", "in_progress"}:
        raise HTTPException(status_code=409, detail="Este plano não aceita novos procedimentos.")
    if plan.version != payload.plan_version:
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de adicionar procedimentos.")
    procedure = TreatmentPlanProcedure(
        plan_id=plan.id,
        name=payload.name,
        category=payload.category,
        description=payload.description,
        tooth_number=payload.tooth_number,
        surfaces=payload.surfaces,
        priority=payload.priority,
        stage=payload.stage,
        notes=payload.notes,
        sort_order=payload.sort_order,
    )
    db.add(procedure)
    db.flush()
    result = db.execute(
        update(TreatmentPlan)
        .where(TreatmentPlan.id == plan.id, TreatmentPlan.version == payload.plan_version)
        .values(version=TreatmentPlan.version + 1, updated_at=func.now())
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de adicionar procedimentos.")
    _record_treatment_plan_audit(
        db, plan.id, user, "procedure_added", f"Procedimento “{procedure.name}” incluído.",
        procedure_id=procedure.id, after_data=_treatment_procedure_snapshot(procedure),
    )
    db.commit()
    db.refresh(procedure)
    return DentistTreatmentProcedureResponse(
        id=procedure.id,
        version=procedure.version,
        name=procedure.name,
        category=procedure.category,
        description=procedure.description,
        tooth_number=procedure.tooth_number,
        surfaces=procedure.surfaces,
        priority=procedure.priority,
        stage=procedure.stage,
        notes=procedure.notes,
        status=procedure.status,
        sort_order=procedure.sort_order,
        completed_odontogram_entry_id=procedure.completed_odontogram_entry_id,
        created_at=procedure.created_at,
        updated_at=procedure.updated_at,
    )


@router.patch(
    "/treatment-plans/{plan_id}/procedures/{procedure_id}",
    response_model=DentistTreatmentProcedureResponse,
)
def update_dentist_treatment_plan_procedure(
    plan_id: int,
    procedure_id: int,
    payload: DentistTreatmentProcedureUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistTreatmentProcedureResponse:
    plan, _patient_name, _dentist_name = _get_dentist_treatment_plan(plan_id, db, user)
    procedure = db.query(TreatmentPlanProcedure).filter(
        TreatmentPlanProcedure.id == procedure_id,
        TreatmentPlanProcedure.plan_id == plan.id,
    ).first()
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado.")
    if plan.version != payload.plan_version:
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de salvar o procedimento.")
    if procedure.version != payload.version:
        raise HTTPException(status_code=409, detail="O procedimento mudou. Atualize antes de salvar.")
    if plan.status not in {"draft", "in_progress"} or procedure.status in {"completed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Este procedimento não pode mais ser alterado.")

    allowed_status_changes = {
        "planned": {"planned", "in_progress", "cancelled"},
        "in_progress": {"in_progress", "cancelled", "completed"},
    }
    if payload.status not in allowed_status_changes.get(procedure.status, set()):
        raise HTTPException(status_code=422, detail="Transição de situação não permitida.")
    if payload.status == "in_progress" and plan.status != "in_progress":
        raise HTTPException(status_code=409, detail="Inicie o plano antes de começar um procedimento.")

    completion_entry = None
    if payload.status == "completed":
        completion_query = db.query(DentalChartEntry).filter(
            DentalChartEntry.id == payload.completed_odontogram_entry_id,
            DentalChartEntry.clinic_id == user.clinic_id,
            DentalChartEntry.patient_id == plan.patient_id,
            DentalChartEntry.dentist_id == user.id,
            DentalChartEntry.record_type == "procedure",
            DentalChartEntry.status == "completed",
        )
        if payload.tooth_number:
            completion_query = completion_query.filter(
                DentalChartEntry.tooth_number == payload.tooth_number,
                DentalChartEntry.surfaces == payload.surfaces,
            )
        completion_entry = completion_query.first()
        if completion_entry is None:
            raise HTTPException(
                status_code=422,
                detail="Vincule um procedimento concluído no odontograma com o mesmo dente e superfícies.",
            )
        if completion_entry.label.casefold() != payload.name.casefold():
            raise HTTPException(
                status_code=422,
                detail="O nome do procedimento deve corresponder ao registro clínico concluído.",
            )
        appointment = db.query(Appointment).filter(
            Appointment.id == completion_entry.appointment_id,
            Appointment.patient_id == plan.patient_id,
            Appointment.clinic_id == user.clinic_id,
            Appointment.dentist_id == user.id,
            Appointment.status == "Concluída",
        ).first()
        if appointment is None:
            raise HTTPException(
                status_code=422,
                detail="O registro do odontograma precisa estar ligado a um atendimento concluído.",
            )
        newer_entry = db.query(DentalChartEntry.id).filter(
            DentalChartEntry.supersedes_entry_id == completion_entry.id
        ).first()
        if newer_entry is not None:
            raise HTTPException(status_code=409, detail="O registro do odontograma já foi atualizado.")

    before = _treatment_procedure_snapshot(procedure)
    updates = {
        "name": payload.name,
        "category": payload.category,
        "description": payload.description,
        "tooth_number": payload.tooth_number,
        "surfaces": payload.surfaces,
        "priority": payload.priority,
        "stage": payload.stage,
        "notes": payload.notes,
        "status": payload.status,
        "sort_order": payload.sort_order,
        "completed_odontogram_entry_id": (
            completion_entry.id if completion_entry is not None else None
        ),
    }
    result = db.execute(
        update(TreatmentPlanProcedure)
        .where(
            TreatmentPlanProcedure.id == procedure.id,
            TreatmentPlanProcedure.version == payload.version,
        )
        .values(**updates, version=TreatmentPlanProcedure.version + 1, updated_at=func.now())
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="O procedimento mudou. Atualize antes de salvar.")
    db.refresh(procedure)
    _record_treatment_plan_audit(
        db, plan.id, user, "procedure_updated",
        f"Procedimento “{procedure.name}” atualizado.",
        procedure_id=procedure.id,
        before_data=before,
        after_data=_treatment_procedure_snapshot(procedure),
    )

    procedures = db.query(TreatmentPlanProcedure).filter(
        TreatmentPlanProcedure.plan_id == plan.id
    ).all()
    eligible = [item for item in procedures if item.status != "cancelled"]
    plan_completed = (
        eligible
        and all(item.status == "completed" for item in eligible)
        and plan.status == "in_progress"
    )
    updated_plan = db.execute(
        update(TreatmentPlan)
        .where(TreatmentPlan.id == plan.id, TreatmentPlan.version == payload.plan_version)
        .values(
            status="completed" if plan_completed else plan.status,
            version=TreatmentPlan.version + 1,
            updated_at=func.now(),
        )
    )
    if updated_plan.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de salvar o procedimento.")
    db.refresh(plan)
    if plan_completed:
        _record_treatment_plan_audit(
            db, plan.id, user, "plan_completed",
            "Plano concluído após a conclusão clínica de todos os procedimentos ativos.",
            before_data={"status": "in_progress"},
            after_data={"status": "completed"},
        )

    db.commit()
    db.refresh(procedure)
    return DentistTreatmentProcedureResponse(
        id=procedure.id,
        version=procedure.version,
        name=procedure.name,
        category=procedure.category,
        description=procedure.description,
        tooth_number=procedure.tooth_number,
        surfaces=procedure.surfaces,
        priority=procedure.priority,
        stage=procedure.stage,
        notes=procedure.notes,
        status=procedure.status,
        sort_order=procedure.sort_order,
        completed_odontogram_entry_id=procedure.completed_odontogram_entry_id,
        created_at=procedure.created_at,
        updated_at=procedure.updated_at,
    )


@router.delete(
    "/treatment-plans/{plan_id}/procedures/{procedure_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_dentist_treatment_plan_procedure(
    plan_id: int,
    procedure_id: int,
    version: int = Query(ge=1),
    plan_version: int = Query(ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> None:
    plan, _patient_name, _dentist_name = _get_dentist_treatment_plan(plan_id, db, user)
    procedure = db.query(TreatmentPlanProcedure).filter(
        TreatmentPlanProcedure.id == procedure_id,
        TreatmentPlanProcedure.plan_id == plan.id,
    ).first()
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedimento não encontrado.")
    if procedure.version != version:
        raise HTTPException(status_code=409, detail="O procedimento mudou. Atualize antes de remover.")
    if plan.version != plan_version:
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de remover o procedimento.")
    if plan.status not in {"draft", "in_progress"} or procedure.status != "planned":
        raise HTTPException(status_code=409, detail="Somente procedimentos ainda planejados podem ser removidos.")
    before = _treatment_procedure_snapshot(procedure)
    procedure_id_value = procedure.id
    summary = f"Procedimento “{procedure.name}” removido do plano."
    _record_treatment_plan_audit(
        db, plan.id, user, "procedure_removed", summary,
        procedure_id=procedure_id_value, before_data=before,
    )
    result = db.execute(
        update(TreatmentPlan)
        .where(TreatmentPlan.id == plan.id, TreatmentPlan.version == plan_version)
        .values(version=TreatmentPlan.version + 1, updated_at=func.now())
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="O plano mudou. Atualize antes de remover o procedimento.")
    db.delete(procedure)
    db.commit()


@router.get(
    "/treatment-plans/{plan_id}/history",
    response_model=list[DentistTreatmentPlanAuditResponse],
)
def dentist_treatment_plan_history(
    plan_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> list[DentistTreatmentPlanAuditResponse]:
    _get_dentist_treatment_plan(plan_id, db, user)
    rows = (
        db.query(TreatmentPlanAudit, User.name)
        .join(User, User.id == TreatmentPlanAudit.dentist_id)
        .filter(TreatmentPlanAudit.plan_id == plan_id)
        .order_by(TreatmentPlanAudit.created_at.desc(), TreatmentPlanAudit.id.desc())
        .limit(200)
        .all()
    )
    return [
        DentistTreatmentPlanAuditResponse(
            id=entry.id,
            dentist_id=entry.dentist_id,
            dentist_name=dentist_name,
            procedure_id=entry.procedure_id,
            action=entry.action,
            summary=entry.summary,
            before_data=entry.before_data,
            after_data=entry.after_data,
            created_at=entry.created_at,
        )
        for entry, dentist_name in rows
    ]


def _clinical_document_response(
    document: ClinicalDocument,
    patient_name: str,
    dentist_name: str,
    db: Session,
) -> DentistClinicalDocumentResponse:
    latest_history_id = db.query(func.max(ClinicalDocumentAudit.id)).filter(
        ClinicalDocumentAudit.document_id == document.id
    ).scalar()
    return DentistClinicalDocumentResponse(
        id=document.id,
        version=document.version,
        patient_id=document.patient_id,
        appointment_id=document.appointment_id,
        document_type=document.document_type,
        title=document.title,
        content=document.content,
        status="draft",
        patient={"id": document.patient_id, "name": patient_name},
        dentist_id=document.dentist_id,
        dentist_name=dentist_name,
        created_at=document.created_at,
        updated_at=document.updated_at,
        latest_history_id=latest_history_id,
    )


def _get_dentist_clinical_document(document_id: int, db: Session, user: User):
    row = (
        db.query(ClinicalDocument, Patient.name, User.name)
        .join(Patient, Patient.id == ClinicalDocument.patient_id)
        .join(User, User.id == ClinicalDocument.dentist_id)
        .filter(
            ClinicalDocument.id == document_id,
            ClinicalDocument.clinic_id == user.clinic_id,
            ClinicalDocument.dentist_id == user.id,
            Patient.clinic_id == user.clinic_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Rascunho não encontrado.")
    return row


def _validate_document_appointment(
    patient_id: int,
    appointment_id: int | None,
    db: Session,
    user: User,
) -> None:
    if appointment_id is None:
        return
    appointment = db.query(Appointment.id).filter(
        Appointment.id == appointment_id,
        Appointment.patient_id == patient_id,
        Appointment.dentist_id == user.id,
        Appointment.clinic_id == user.clinic_id,
    ).first()
    if appointment is None:
        raise HTTPException(
            status_code=404,
            detail="Atendimento não encontrado para este paciente.",
        )


def _record_clinical_document_audit(
    db: Session,
    document_id: int,
    user: User,
    action: str,
    summary: str,
) -> None:
    db.add(
        ClinicalDocumentAudit(
            document_id=document_id,
            dentist_id=user.id,
            action=action,
            summary=summary,
        )
    )


@router.get(
    "/documents",
    response_model=DentistClinicalDocumentRegistryResponse,
)
def dentist_clinical_documents(
    q: str | None = Query(default=None, max_length=160),
    document_type: str | None = Query(
        default=None,
        pattern="^(prescription|certificate|attendance_declaration|referral|other)$",
    ),
    patient_id: int | None = Query(default=None, ge=1),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistClinicalDocumentRegistryResponse:
    query = (
        db.query(ClinicalDocument, Patient.name, User.name)
        .join(Patient, Patient.id == ClinicalDocument.patient_id)
        .join(User, User.id == ClinicalDocument.dentist_id)
        .filter(
            ClinicalDocument.clinic_id == user.clinic_id,
            ClinicalDocument.dentist_id == user.id,
            Patient.clinic_id == user.clinic_id,
        )
    )
    documents = query.order_by(
        ClinicalDocument.updated_at.desc(), ClinicalDocument.id.desc()
    ).all()
    if q and q.strip():
        term = _normalized_search(q)
        digits = re.sub(r"\D", "", q)
        documents = [
            row for row in documents
            if term in _normalized_search(row[0].title)
            or term in _normalized_search(row[1])
            or (digits and (
                digits in str(row[0].id) or digits in str(row[0].patient_id)
            ))
        ]
    if document_type:
        documents = [row for row in documents if row[0].document_type == document_type]
    if patient_id is not None:
        documents = [row for row in documents if row[0].patient_id == patient_id]

    total = len(documents)
    return DentistClinicalDocumentRegistryResponse(
        items=[
            _clinical_document_response(document, patient_name, dentist_name, db)
            for document, patient_name, dentist_name in documents[offset:offset + limit]
        ],
        total=total,
        metrics=DentistClinicalDocumentSummary(
            drafts=total,
            issued=None,
        ),
    )


@router.post(
    "/documents",
    response_model=DentistClinicalDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_dentist_clinical_document_draft(
    payload: DentistClinicalDocumentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistClinicalDocumentResponse:
    patient = _authorize_dentist_patient(payload.patient_id, db, user)
    _validate_document_appointment(
        patient.id, payload.appointment_id, db, user
    )
    document = ClinicalDocument(
        clinic_id=user.clinic_id,
        patient_id=patient.id,
        dentist_id=user.id,
        appointment_id=payload.appointment_id,
        document_type=payload.document_type,
        title=payload.title,
        content=payload.content,
        status="draft",
    )
    db.add(document)
    db.flush()
    _record_clinical_document_audit(
        db, document.id, user, "created", "Rascunho criado."
    )
    try:
        db.commit()
        db.refresh(document)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível salvar o rascunho.",
        ) from error
    return _clinical_document_response(document, patient.name, user.name, db)


@router.get(
    "/documents/{document_id}",
    response_model=DentistClinicalDocumentResponse,
)
def get_dentist_clinical_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistClinicalDocumentResponse:
    document, patient_name, dentist_name = _get_dentist_clinical_document(
        document_id, db, user
    )
    return _clinical_document_response(document, patient_name, dentist_name, db)


@router.patch(
    "/documents/{document_id}",
    response_model=DentistClinicalDocumentResponse,
)
def update_dentist_clinical_document_draft(
    document_id: int,
    payload: DentistClinicalDocumentUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> DentistClinicalDocumentResponse:
    document, _patient_name, _dentist_name = _get_dentist_clinical_document(
        document_id, db, user
    )
    if document.version != payload.version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O rascunho foi atualizado. Recarregue antes de salvar.",
        )
    patient = _authorize_dentist_patient(payload.patient_id, db, user)
    _validate_document_appointment(
        patient.id, payload.appointment_id, db, user
    )
    result = db.execute(
        update(ClinicalDocument)
        .where(
            ClinicalDocument.id == document.id,
            ClinicalDocument.dentist_id == user.id,
            ClinicalDocument.version == payload.version,
            ClinicalDocument.status == "draft",
        )
        .values(
            patient_id=patient.id,
            appointment_id=payload.appointment_id,
            document_type=payload.document_type,
            title=payload.title,
            content=payload.content,
            version=ClinicalDocument.version + 1,
            updated_at=func.now(),
        )
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="O rascunho foi atualizado. Recarregue antes de salvar.",
        )
    _record_clinical_document_audit(
        db, document.id, user, "updated", "Rascunho atualizado."
    )
    try:
        db.commit()
        db.refresh(document)
    except IntegrityError as error:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Não foi possível atualizar o rascunho.",
        ) from error
    return _clinical_document_response(document, patient.name, user.name, db)


@router.get(
    "/documents/{document_id}/history",
    response_model=list[DentistClinicalDocumentAuditResponse],
)
def dentist_clinical_document_history(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("dentist")),
) -> list[DentistClinicalDocumentAuditResponse]:
    _get_dentist_clinical_document(document_id, db, user)
    rows = (
        db.query(ClinicalDocumentAudit, User.name)
        .join(User, User.id == ClinicalDocumentAudit.dentist_id)
        .filter(ClinicalDocumentAudit.document_id == document_id)
        .order_by(
            ClinicalDocumentAudit.created_at.desc(),
            ClinicalDocumentAudit.id.desc(),
        )
        .limit(200)
        .all()
    )
    return [
        DentistClinicalDocumentAuditResponse(
            id=entry.id,
            dentist_id=entry.dentist_id,
            dentist_name=dentist_name,
            action=entry.action,
            summary=entry.summary,
            created_at=entry.created_at,
        )
        for entry, dentist_name in rows
    ]
