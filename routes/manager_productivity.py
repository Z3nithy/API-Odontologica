from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from dependencies.autenticacao import require_roles
from models import Appointment, User
from schemas.manager_productivity import (
    ManagerProductivityResponse,
    ProductivityDentistOption,
    ProductivityMetrics,
    ProductivityProfessional,
    ProductivityRecordItem,
    ProductivityRecordList,
    ProductivityStatusCount,
    ProductivityTimelinePoint,
)

router = APIRouter(prefix="/api/manager/productivity", tags=["Produtividade da equipe"])
MAX_PERIOD_DAYS = 366
REBOOKED_STATUS = "Reagendada"
COMPLETED_STATUS = "Concluída"
CANCELLED_STATUS = "Cancelada"
NO_SHOW_STATUS = "Não compareceu"
SUPPORTED_STATUSES = (
    "Agendada",
    "Confirmada",
    "Aguardando chegada",
    "Em espera",
    "Em atendimento",
    COMPLETED_STATUS,
    CANCELLED_STATUS,
    NO_SHOW_STATUS,
    REBOOKED_STATUS,
)


def _percentage(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator * 100 / denominator, 1)


def _metrics(
    appointments: list[Appointment], status_filtered: bool = False
) -> ProductivityMetrics:
    terminal_statuses = (COMPLETED_STATUS, CANCELLED_STATUS, NO_SHOW_STATUS)
    eligible = [
        item
        for item in appointments
        if item.status != REBOOKED_STATUS
        and (item.appointment_date <= date.today() or item.status in terminal_statuses)
    ]
    completed = sum(item.status == COMPLETED_STATUS for item in eligible)
    cancelled = sum(item.status == CANCELLED_STATUS for item in eligible)
    no_show = sum(item.status == NO_SHOW_STATUS for item in eligible)
    scheduled = sum(item.status not in (CANCELLED_STATUS, REBOOKED_STATUS) for item in appointments)
    return ProductivityMetrics(
        appointments_total=len(appointments),
        scheduled=scheduled,
        completed=completed,
        cancelled=cancelled,
        no_show=no_show,
        eligible=len(eligible),
        completion_rate=None if status_filtered else _percentage(completed, len(eligible)),
        cancellation_rate=None if status_filtered else _percentage(cancelled, len(eligible)),
        no_show_rate=None if status_filtered else _percentage(no_show, len(eligible)),
        professionals_with_completed=0,
        planned_completed_hours=round(
            sum(item.duration_minutes for item in eligible if item.status == COMPLETED_STATUS) / 60,
            1,
        ),
    )


def _period_group(days: int) -> str:
    if days <= 31:
        return "day"
    if days <= 180:
        return "week"
    return "month"


def _group_key(day: date, group_by: str) -> date:
    if group_by == "week":
        return day - timedelta(days=day.weekday())
    if group_by == "month":
        return day.replace(day=1)
    return day


def _timeline(
    appointments: list[Appointment], start_date: date, end_date: date, group_by: str
) -> list[ProductivityTimelinePoint]:
    grouped: dict[date, list[Appointment]] = defaultdict(list)
    cursor = start_date
    while cursor <= end_date:
        grouped[_group_key(cursor, group_by)]
        cursor += timedelta(days=1)
    for appointment in appointments:
        if appointment.status != REBOOKED_STATUS:
            grouped[_group_key(appointment.appointment_date, group_by)].append(appointment)

    labels = {
        "day": lambda day: day.strftime("%d/%m"),
        "week": lambda day: f"sem. {day.strftime('%d/%m')}",
        "month": lambda day: day.strftime("%b/%y"),
    }
    return [
        ProductivityTimelinePoint(
            date=period,
            label=labels[group_by](period),
            scheduled=sum(
                item.status not in (CANCELLED_STATUS, REBOOKED_STATUS) for item in items
            ),
            completed=sum(item.status == COMPLETED_STATUS for item in items),
            cancelled=sum(item.status == CANCELLED_STATUS for item in items),
            no_show=sum(item.status == NO_SHOW_STATUS for item in items),
        )
        for period, items in sorted(grouped.items())
    ]


def _query_appointments(
    db: Session,
    clinic_id: int,
    start_date: date,
    end_date: date,
    dentist_ids: list[int],
    appointment_status: str | None,
) -> list[Appointment]:
    query = db.query(Appointment).filter(
        Appointment.clinic_id == clinic_id,
        Appointment.appointment_date >= start_date,
        Appointment.appointment_date <= end_date,
        Appointment.dentist_id.in_(dentist_ids),
    )
    if appointment_status:
        query = query.filter(Appointment.status == appointment_status)
    return query.order_by(Appointment.appointment_date, Appointment.appointment_time).all()


@router.get("", response_model=ManagerProductivityResponse)
def get_manager_productivity(
    start_date: date,
    end_date: date,
    compare: bool = True,
    dentist_ids: str | None = Query(default=None, max_length=1000),
    appointment_status: str | None = Query(default=None, alias="status"),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ManagerProductivityResponse:
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data final deve ser igual ou posterior à inicial.",
        )
    period_days = (end_date - start_date).days + 1
    if period_days > MAX_PERIOD_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"O período não pode ultrapassar {MAX_PERIOD_DAYS} dias.",
        )
    if appointment_status and appointment_status not in SUPPORTED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O status informado não é suportado.",
        )

    dentists = (
        db.query(User)
        .filter(User.clinic_id == manager.clinic_id, User.role == "dentist")
        .order_by(User.name, User.id)
        .all()
    )
    dentist_options = [
        ProductivityDentistOption(
            dentist_id=dentist.id,
            name=dentist.name,
            active=dentist.active,
        )
        for dentist in dentists
    ]
    if dentist_ids:
        try:
            selected_ids = list(dict.fromkeys(int(item) for item in dentist_ids.split(",")))
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A seleção de profissionais é inválida.",
            ) from error
        if not selected_ids or any(item < 1 for item in selected_ids):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Selecione ao menos um profissional válido.",
            )
        visible_ids = {dentist.id for dentist in dentists}
        if any(item not in visible_ids for item in selected_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Um ou mais profissionais não pertencem à clínica.",
            )
        dentists = [dentist for dentist in dentists if dentist.id in selected_ids]
    professional_ids = [dentist.id for dentist in dentists]

    appointments = _query_appointments(
        db, manager.clinic_id, start_date, end_date, professional_ids or [-1], appointment_status
    )
    grouped_professionals: dict[int, list[Appointment]] = defaultdict(list)
    for appointment in appointments:
        grouped_professionals[appointment.dentist_id].append(appointment)

    metric_data = _metrics(appointments, status_filtered=appointment_status is not None)
    professionals = []
    for dentist in dentists:
        rows = grouped_professionals[dentist.id]
        item = _metrics(rows, status_filtered=appointment_status is not None)
        professionals.append(
            ProductivityProfessional(
                dentist_id=dentist.id,
                name=dentist.name,
                active=dentist.active,
                appointments_total=item.appointments_total,
                scheduled=item.scheduled,
                completed=item.completed,
                cancelled=item.cancelled,
                no_show=item.no_show,
                eligible=item.eligible,
                completion_rate=item.completion_rate,
                cancellation_rate=item.cancellation_rate,
                no_show_rate=item.no_show_rate,
                planned_completed_hours=item.planned_completed_hours,
            )
        )
    metric_data.professionals_with_completed = sum(
        item.completed > 0 for item in professionals
    )

    previous_start = start_date - timedelta(days=period_days) if compare else None
    previous_end = start_date - timedelta(days=1) if compare else None
    previous_metrics = None
    if previous_start is not None and previous_end is not None:
        previous_rows = _query_appointments(
            db, manager.clinic_id, previous_start, previous_end, professional_ids or [-1],
            appointment_status,
        )
        previous_metrics = _metrics(previous_rows, status_filtered=appointment_status is not None)
        previous_grouped: dict[int, list[Appointment]] = defaultdict(list)
        for appointment in previous_rows:
            previous_grouped[appointment.dentist_id].append(appointment)
        previous_metrics.professionals_with_completed = sum(
            any(item.status == COMPLETED_STATUS for item in previous_grouped[dentist.id])
            for dentist in dentists
        )

    group_by = _period_group(period_days)
    return ManagerProductivityResponse(
        start_date=start_date,
        end_date=end_date,
        previous_start_date=previous_start,
        previous_end_date=previous_end,
        group_by=group_by,
        metrics=metric_data,
        previous_metrics=previous_metrics,
        professionals=professionals,
        dentist_options=dentist_options,
        timeline=_timeline(appointments, start_date, end_date, group_by),
        status_counts=[
            ProductivityStatusCount(
                status=appointment_status or appointment_state,
                count=(
                    sum(item.status == appointment_state for item in appointments)
                    if appointment_status is None
                    else sum(item.status == appointment_status for item in appointments)
                ),
            )
            for appointment_state in SUPPORTED_STATUSES
            if appointment_status is None or appointment_state == appointment_status
        ],
        available_statuses=list(SUPPORTED_STATUSES),
    )


@router.get("/records", response_model=ProductivityRecordList)
def get_manager_productivity_records(
    start_date: date,
    end_date: date,
    metric: str = Query(pattern="^(scheduled|eligible|completed|cancelled|no_show)$"),
    dentist_ids: str | None = Query(default=None, max_length=1000),
    appointment_status: str | None = Query(default=None, alias="status"),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
    db: Session = Depends(get_db),
    manager: User = Depends(require_roles("manager")),
) -> ProductivityRecordList:
    if end_date < start_date:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A data final deve ser igual ou posterior à inicial.",
        )
    if (end_date - start_date).days + 1 > MAX_PERIOD_DAYS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"O período não pode ultrapassar {MAX_PERIOD_DAYS} dias.",
        )
    if appointment_status and appointment_status not in SUPPORTED_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="O status informado não é suportado.",
        )

    dentists = db.query(User).filter(
        User.clinic_id == manager.clinic_id,
        User.role == "dentist",
    )
    if dentist_ids:
        try:
            selected_ids = list(dict.fromkeys(int(item) for item in dentist_ids.split(",")))
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A seleção de profissionais é inválida.",
            ) from error
        visible_ids = {row.id for row in dentists.all()}
        if not selected_ids or any(item < 1 or item not in visible_ids for item in selected_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Um ou mais profissionais não pertencem à clínica.",
            )
        dentist_ids_for_query = selected_ids
    else:
        dentist_ids_for_query = [row.id for row in dentists.all()]

    query = (
        db.query(Appointment, User)
        .join(User, User.id == Appointment.dentist_id)
        .filter(
            Appointment.clinic_id == manager.clinic_id,
            User.clinic_id == manager.clinic_id,
            User.role == "dentist",
            Appointment.dentist_id.in_(dentist_ids_for_query or [-1]),
            Appointment.appointment_date >= start_date,
            Appointment.appointment_date <= end_date,
        )
    )
    if appointment_status:
        query = query.filter(Appointment.status == appointment_status)
    if metric == "scheduled":
        query = query.filter(Appointment.status.notin_((CANCELLED_STATUS, REBOOKED_STATUS)))
    elif metric == "eligible":
        query = query.filter(Appointment.status != REBOOKED_STATUS).filter(
            (Appointment.appointment_date <= date.today())
            | Appointment.status.in_((COMPLETED_STATUS, CANCELLED_STATUS, NO_SHOW_STATUS))
        )
    elif metric == "completed":
        query = query.filter(Appointment.status == COMPLETED_STATUS)
    elif metric == "cancelled":
        query = query.filter(Appointment.status == CANCELLED_STATUS)
    elif metric == "no_show":
        query = query.filter(Appointment.status == NO_SHOW_STATUS)

    total = query.count()
    rows = (
        query.order_by(
            Appointment.appointment_date,
            Appointment.appointment_time,
            Appointment.id,
        )
        .offset(offset)
        .limit(limit)
        .all()
    )
    return ProductivityRecordList(
        items=[
            ProductivityRecordItem(
                appointment_id=appointment.id,
                appointment_date=appointment.appointment_date,
                appointment_time=appointment.appointment_time,
                dentist_id=dentist.id,
                dentist_name=dentist.name,
                status=appointment.status,
                duration_minutes=appointment.duration_minutes,
            )
            for appointment, dentist in rows
        ],
        total=total,
        offset=offset,
        limit=limit,
    )
