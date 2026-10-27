from datetime import date, time

from pydantic import BaseModel


class ProductivityMetrics(BaseModel):
    appointments_total: int
    scheduled: int
    completed: int
    cancelled: int
    no_show: int
    eligible: int
    completion_rate: float | None
    cancellation_rate: float | None
    no_show_rate: float | None
    professionals_with_completed: int
    planned_completed_hours: float
    occupation_available: bool = False


class ProductivityProfessional(BaseModel):
    dentist_id: int
    name: str
    active: bool
    appointments_total: int
    scheduled: int
    completed: int
    cancelled: int
    no_show: int
    eligible: int
    completion_rate: float | None
    cancellation_rate: float | None
    no_show_rate: float | None
    planned_completed_hours: float


class ProductivityTimelinePoint(BaseModel):
    date: date
    label: str
    scheduled: int
    completed: int
    cancelled: int
    no_show: int


class ProductivityStatusCount(BaseModel):
    status: str
    count: int


class ProductivityDentistOption(BaseModel):
    dentist_id: int
    name: str
    active: bool


class ProductivityRecordItem(BaseModel):
    appointment_id: int
    appointment_date: date
    appointment_time: time
    dentist_id: int
    dentist_name: str
    status: str
    duration_minutes: int


class ProductivityRecordList(BaseModel):
    items: list[ProductivityRecordItem]
    total: int
    offset: int
    limit: int


class ManagerProductivityResponse(BaseModel):
    start_date: date
    end_date: date
    previous_start_date: date | None
    previous_end_date: date | None
    group_by: str
    metrics: ProductivityMetrics
    previous_metrics: ProductivityMetrics | None
    professionals: list[ProductivityProfessional]
    dentist_options: list[ProductivityDentistOption]
    timeline: list[ProductivityTimelinePoint]
    status_counts: list[ProductivityStatusCount]
    available_statuses: list[str]
