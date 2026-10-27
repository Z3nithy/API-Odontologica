from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
    Index,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint("duration_minutes > 0", name="ck_appointment_duration_positive"),
        Index("ix_appointment_clinic_date", "clinic_id", "appointment_date"),
        Index("ix_appointment_dentist_date", "dentist_id", "appointment_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    clinic_id: Mapped[int] = mapped_column(ForeignKey("clinics.id"), index=True)
    patient_id: Mapped[int] = mapped_column(ForeignKey("patients.id"), index=True)
    dentist_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    appointment_date: Mapped[date] = mapped_column(Date, nullable=False)
    appointment_time: Mapped[time] = mapped_column(Time, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    procedure: Mapped[str] = mapped_column(String(120), nullable=False)
    confirmation_status: Mapped[str] = mapped_column(String(24), default="Pendente")
    status: Mapped[str] = mapped_column(String(32), default="Agendada", index=True)
    contact_channel: Mapped[str | None] = mapped_column(String(32), nullable=True)
    administrative_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    arrival_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
